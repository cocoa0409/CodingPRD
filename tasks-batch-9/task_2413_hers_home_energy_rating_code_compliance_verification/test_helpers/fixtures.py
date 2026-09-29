"""Composite state builders and pytest fixtures.

The harness relaunches the API server with an empty database before every
individual test, so every precondition here is built from scratch through the
PRD's own endpoints — there is no seeding, no direct database access and no
mocking anywhere.

Layout of this module:

* ``api`` / ``admin`` — the client and provider-staff headers.
* Thin per-endpoint action helpers (``create_builder``, ``confirm_rating``, ...)
  that validate the envelope and return the ``data`` payload.
* Read-back helpers (``get_rating``, ``get_builder``, ...) that always read as
  ``RatingProviderAdmin``, which §2.1 allows to act on any row.
* ``RatingWorld`` / ``SampleWorld`` composite builders that assemble the long
  onboarding chains the suite needs, and the pytest fixtures layered on them:

  - ``rating_world``            builder + subdivision + raters + plan + lot + PROJECTED rating
  - ``confirmed_passing_world`` the same, driven through a passing FINAL checkpoint and confirmation
  - ``confirmed_failing_world`` the same, but with a failing blower-door reading
  - ``registered_world``        confirmed, submitted and accepted by the registry
  - ``issued_tax_credit_world`` registered plus an ISSUED TAX_CREDIT_45L package
  - ``sample_world``            sampling-enabled subdivision with three FORMING members
  - ``selected_sample_world``   the same, after the tested-home selector has run
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_paginated, validate_success

from . import factories
from .api_client import ApiClient
from .test_users import (
    ADMIN_HEADERS,
    make_builder_rep_headers,
    make_certified_rater_headers,
    make_field_inspector_headers,
    make_qa_designee_headers,
)


# ---------------------------------------------------------------- base fixtures
@pytest.fixture
def api() -> ApiClient:
    """Client pointed at the running server (base URL injected by the runner)."""
    return ApiClient()


@pytest.fixture
def admin() -> Dict[str, str]:
    """Provider back-office headers (§2.1: opaque `X-User-ID`)."""
    return ADMIN_HEADERS


# ------------------------------------------------------------- action helpers
def create_builder(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_builder(factories.builder_payload(**kwargs), ADMIN_HEADERS)
    return validate_success(response, 201)


def create_subdivision(api: ApiClient, builder_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_subdivision(
        factories.subdivision_payload(builder_id, **kwargs), ADMIN_HEADERS
    )
    return validate_success(response, 201)


def create_rater(api: ApiClient, **kwargs: Any) -> Dict[str, Any]:
    response = api.create_rater(factories.rater_payload(**kwargs), ADMIN_HEADERS)
    return validate_success(response, 201)


def create_plan_model(
    api: ApiClient, subdivision_id: str, rater_id: str, **overrides: Any
) -> Dict[str, Any]:
    response = api.create_plan_model(
        factories.plan_model_payload(subdivision_id, **overrides),
        make_certified_rater_headers(rater_id),
    )
    return validate_success(response, 201)


def create_home(
    api: ApiClient,
    subdivision_id: str,
    plan_model_id: str,
    builder_id: str,
    **kwargs: Any,
) -> Dict[str, Any]:
    response = api.create_home(
        factories.home_payload(subdivision_id, plan_model_id, **kwargs),
        make_builder_rep_headers(builder_id),
    )
    return validate_success(response, 201)


def create_rating(
    api: ApiClient, home_id: str, rater_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api.create_rating(
        factories.rating_payload(home_id, rater_id, **kwargs),
        make_certified_rater_headers(rater_id),
    )
    return validate_success(response, 201)


def schedule_inspection(
    api: ApiClient, rating_id: str, inspector_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api.create_inspection(
        factories.inspection_payload(rating_id, inspector_id, **kwargs),
        make_field_inspector_headers(inspector_id),
    )
    return validate_success(response, 201)


def record_test(
    api: ApiClient, inspection_id: str, inspector_id: str, test_type: str, measured_value: float
) -> Dict[str, Any]:
    response = api.create_diagnostic_test(
        inspection_id,
        factories.diagnostic_test_payload(test_type, measured_value),
        make_field_inspector_headers(inspector_id),
    )
    return validate_success(response, 201)


def complete_inspection(api: ApiClient, inspection_id: str, inspector_id: str) -> Dict[str, Any]:
    response = api.complete_inspection(
        inspection_id, make_field_inspector_headers(inspector_id)
    )
    return validate_success(response, 200)


def confirm_rating(api: ApiClient, rating_id: str, rater_id: str) -> Dict[str, Any]:
    response = api.confirm_rating(rating_id, make_certified_rater_headers(rater_id))
    return validate_success(response, 200)


def submit_to_registry(api: ApiClient, rating_id: str, rater_id: str) -> Dict[str, Any]:
    response = api.submit_rating_to_registry(
        rating_id, make_certified_rater_headers(rater_id)
    )
    return validate_success(response, 200)


def registry_decision(api: ApiClient, rating_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api.record_registry_decision(
        rating_id, factories.registry_decision_payload(**kwargs), ADMIN_HEADERS
    )
    return validate_success(response, 200)


def void_rating(api: ApiClient, rating_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api.void_rating(rating_id, factories.void_payload(**kwargs), ADMIN_HEADERS)
    return validate_success(response, 200)


def create_sample_set(api: ApiClient, subdivision_id: str, rater_id: str, **kwargs: Any):
    response = api.create_sample_set(
        factories.sample_set_payload(subdivision_id, **kwargs),
        make_certified_rater_headers(rater_id),
    )
    return validate_success(response, 201)


def add_sample_member(
    api: ApiClient, sample_set_id: str, home_id: str, rater_id: str
) -> Dict[str, Any]:
    """Add a home, re-reading the set's `version` first as §2.9 requires."""
    current = get_sample_set(api, sample_set_id)
    response = api.add_sample_set_home(
        sample_set_id,
        factories.sample_set_membership_payload(home_id, current["version"]),
        make_certified_rater_headers(rater_id),
    )
    return validate_success(response, 201)


def withdraw_sample_member(
    api: ApiClient, sample_set_id: str, home_id: str, rater_id: str
) -> Dict[str, Any]:
    current = get_sample_set(api, sample_set_id)
    response = api.withdraw_sample_set_home(
        sample_set_id,
        home_id,
        factories.sample_set_withdraw_payload(current["version"]),
        make_certified_rater_headers(rater_id),
    )
    return validate_success(response, 200)


def select_sample_set(api: ApiClient, sample_set_id: str) -> Dict[str, Any]:
    return validate_success(api.select_sample_set(sample_set_id, ADMIN_HEADERS), 200)


def close_sample_set(api: ApiClient, sample_set_id: str) -> Dict[str, Any]:
    return validate_success(api.close_sample_set(sample_set_id, ADMIN_HEADERS), 200)


def assign_qa_review(
    api: ApiClient, rating_id: str, reviewer_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api.create_qa_review(
        factories.qa_review_payload(rating_id, reviewer_id, **kwargs), ADMIN_HEADERS
    )
    return validate_success(response, 201)


def complete_qa_review(
    api: ApiClient, qa_review_id: str, reviewer_id: str, result: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api.complete_qa_review(
        qa_review_id,
        factories.qa_review_completion_payload(result, **kwargs),
        make_qa_designee_headers(reviewer_id),
    )
    return validate_success(response, 200)


def corrective_actions_of(api: ApiClient, rating_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_corrective_actions(rating_id, ADMIN_HEADERS))
    return data


def submit_corrective_action(
    api: ApiClient, corrective_action_id: str, builder_id: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api.submit_corrective_action(
        corrective_action_id,
        factories.corrective_action_submission_payload(**kwargs),
        make_builder_rep_headers(builder_id),
    )
    return validate_success(response, 200)


def review_corrective_action(
    api: ApiClient, corrective_action_id: str, decision: str, **kwargs: Any
) -> Dict[str, Any]:
    response = api.review_corrective_action(
        corrective_action_id,
        factories.corrective_action_review_payload(decision, **kwargs),
        ADMIN_HEADERS,
    )
    return validate_success(response, 200)


def draft_package(
    api: ApiClient, rating_id: str, builder_id: str, package_type: str = "TAX_CREDIT_45L"
) -> Dict[str, Any]:
    """Draft a package, re-reading the rating's `version` first (§2.9)."""
    rating = get_rating(api, rating_id)
    response = api.create_document_package(
        factories.document_package_payload(
            rating_id, rating["version"], package_type=package_type
        ),
        make_builder_rep_headers(builder_id),
    )
    return validate_success(response, 201)


def issue_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return validate_success(api.issue_document_package(package_id, ADMIN_HEADERS), 200)


def reinstate_rater(api: ApiClient, rater_id: str, **kwargs: Any) -> Dict[str, Any]:
    response = api.reinstate_rater(rater_id, factories.reinstate_payload(**kwargs), ADMIN_HEADERS)
    return validate_success(response, 200)


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    response = api.set_clock(factories.clock_payload(to_iso8601), ADMIN_HEADERS)
    return validate_success(response, 200)


# --------------------------------------------------------------- read helpers
def get_builder(api: ApiClient, builder_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_builder(builder_id, ADMIN_HEADERS))


def get_subdivision(api: ApiClient, subdivision_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_subdivision(subdivision_id, ADMIN_HEADERS))


def get_home(api: ApiClient, home_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_home(home_id, ADMIN_HEADERS))


def get_rater(api: ApiClient, rater_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rater(rater_id, ADMIN_HEADERS))


def get_rating(api: ApiClient, rating_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_rating(rating_id, ADMIN_HEADERS))


def get_inspection(api: ApiClient, inspection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_inspection(inspection_id, ADMIN_HEADERS))


def get_sample_set(api: ApiClient, sample_set_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_sample_set(sample_set_id, ADMIN_HEADERS))


def get_qa_review(api: ApiClient, qa_review_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_qa_review(qa_review_id, ADMIN_HEADERS))


def list_packages(api: ApiClient, rating_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_document_packages(rating_id, ADMIN_HEADERS))
    return data


def list_diagnostic_tests(api: ApiClient, inspection_id: str) -> List[Dict[str, Any]]:
    data, _meta = validate_paginated(api.list_diagnostic_tests(inspection_id, ADMIN_HEADERS))
    return data


# ------------------------------------------------------------ composite worlds
@dataclass
class RatingWorld:
    """One builder, one subdivision, the certified people, one plan, one lot and
    (optionally) one rating file on it."""

    builder: Dict[str, Any]
    subdivision: Dict[str, Any]
    rater: Dict[str, Any]
    inspector: Dict[str, Any]
    qa_designee: Optional[Dict[str, Any]] = None
    plan_model: Optional[Dict[str, Any]] = None
    home: Optional[Dict[str, Any]] = None
    rating: Optional[Dict[str, Any]] = None
    inspections: List[Dict[str, Any]] = field(default_factory=list)

    # ids -------------------------------------------------------------------
    @property
    def builder_id(self) -> str:
        return self.builder["id"]

    @property
    def subdivision_id(self) -> str:
        return self.subdivision["id"]

    @property
    def rater_id(self) -> str:
        return self.rater["id"]

    @property
    def inspector_id(self) -> str:
        return self.inspector["id"]

    @property
    def qa_designee_id(self) -> str:
        assert self.qa_designee is not None, "world was built without a QA designee"
        return self.qa_designee["id"]

    @property
    def plan_model_id(self) -> str:
        return self.plan_model["id"]

    @property
    def home_id(self) -> str:
        return self.home["id"]

    @property
    def rating_id(self) -> str:
        return self.rating["id"]

    @property
    def inspection_id(self) -> str:
        return self.inspections[-1]["id"]

    # headers ---------------------------------------------------------------
    @property
    def rater_headers(self) -> Dict[str, str]:
        return make_certified_rater_headers(self.rater_id)

    @property
    def inspector_headers(self) -> Dict[str, str]:
        return make_field_inspector_headers(self.inspector_id)

    @property
    def qa_headers(self) -> Dict[str, str]:
        return make_qa_designee_headers(self.qa_designee_id)

    @property
    def rep_headers(self) -> Dict[str, str]:
        return make_builder_rep_headers(self.builder_id)


def build_rating_world(
    api: ApiClient,
    *,
    builder_name: str = "Anchor Homes",
    builder_type: str = "PRODUCTION",
    utility_program_budget_cents: int = 250000,
    subdivision_name: str = "Mill Race",
    code_edition: str = "IECC_2021",
    climate_zone: str = "CZ4",
    sampling_enabled: bool = False,
    compliance_path_preference: str = "ERI_PATH",
    plan_overrides: Optional[Dict[str, Any]] = None,
    lot_number: str = "L-1001",
    permit_date: str = "2026-08-10",
    with_qa_designee: bool = True,
    with_home: bool = True,
    with_rating: bool = True,
    rater_cert_expires_at: str = "2027-06-30T00:00:00Z",
    inspector_cert_expires_at: str = "2027-06-30T00:00:00Z",
) -> RatingWorld:
    """Tier 2 builder: the full entity hierarchy down to a PROJECTED rating."""
    builder = create_builder(
        api,
        name=builder_name,
        builder_type=builder_type,
        utility_program_budget_cents=utility_program_budget_cents,
    )
    subdivision = create_subdivision(
        api,
        builder["id"],
        name=subdivision_name,
        code_edition=code_edition,
        climate_zone=climate_zone,
        sampling_enabled=sampling_enabled,
        compliance_path_preference=compliance_path_preference,
    )
    rater = create_rater(
        api,
        full_name="Rae Tarrant",
        cert_level="RATER",
        cert_expires_at=rater_cert_expires_at,
    )
    inspector = create_rater(
        api,
        full_name="Ines Pike",
        cert_level="RATING_FIELD_INSPECTOR",
        cert_expires_at=inspector_cert_expires_at,
    )
    qa_designee = (
        create_rater(api, full_name="Quill Adaire", cert_level="QA_DESIGNEE")
        if with_qa_designee
        else None
    )
    plan_model = create_plan_model(
        api, subdivision["id"], rater["id"], **(plan_overrides or {})
    )

    world = RatingWorld(
        builder=builder,
        subdivision=subdivision,
        rater=rater,
        inspector=inspector,
        qa_designee=qa_designee,
        plan_model=plan_model,
    )
    if with_home:
        world.home = create_home(
            api,
            subdivision["id"],
            plan_model["id"],
            builder["id"],
            lot_number=lot_number,
            permit_date=permit_date,
        )
        if with_rating:
            world.rating = create_rating(api, world.home["id"], rater["id"])
    return world


def run_final_checkpoint(
    api: ApiClient,
    world: RatingWorld,
    *,
    blower_door: Optional[float] = 1080,
    duct_leakage: Optional[float] = 96,
    air_handler_installed: bool = True,
    scheduled_start_utc: str = "2026-08-21T09:00:00Z",
    scheduled_end_utc: str = "2026-08-21T11:00:00Z",
    complete: bool = True,
) -> Dict[str, Any]:
    """Schedule a FINAL checkpoint, record the governing measurements and close it."""
    inspection = schedule_inspection(
        api,
        world.rating_id,
        world.inspector_id,
        checkpoint="FINAL",
        scheduled_start_utc=scheduled_start_utc,
        scheduled_end_utc=scheduled_end_utc,
        air_handler_installed=air_handler_installed,
    )
    if blower_door is not None:
        record_test(api, inspection["id"], world.inspector_id, "BLOWER_DOOR", blower_door)
    if duct_leakage is not None:
        record_test(
            api, inspection["id"], world.inspector_id, "DUCT_LEAKAGE_TOTAL", duct_leakage
        )
    if complete:
        inspection = complete_inspection(api, inspection["id"], world.inspector_id)
    world.inspections.append(inspection)
    return inspection


def build_confirmed_world(
    api: ApiClient,
    *,
    blower_door: float = 1080,
    duct_leakage: float = 96,
    air_handler_installed: bool = True,
    **world_kwargs: Any,
) -> RatingWorld:
    """Tier 3 shortcut: a world whose rating has been confirmed from a FINAL
    checkpoint carrying the two governing measurements."""
    world = build_rating_world(api, **world_kwargs)
    run_final_checkpoint(
        api,
        world,
        blower_door=blower_door,
        duct_leakage=duct_leakage,
        air_handler_installed=air_handler_installed,
    )
    world.rating = confirm_rating(api, world.rating_id, world.rater_id)
    return world


def build_registered_world(
    api: ApiClient,
    *,
    confirmation_number: str = "RESNET-2026-004417",
    **kwargs: Any,
) -> RatingWorld:
    """Tier 5 shortcut: confirmed, submitted and accepted by the registry."""
    world = build_confirmed_world(api, **kwargs)
    submit_to_registry(api, world.rating_id, world.rater_id)
    world.rating = registry_decision(
        api, world.rating_id, outcome="ACCEPT", confirmation_number=confirmation_number
    )
    return world


def build_issued_package_world(
    api: ApiClient,
    *,
    package_type: str = "TAX_CREDIT_45L",
    register: bool = False,
    **kwargs: Any,
):
    """Tier 4 shortcut: a passing rating with one ISSUED package.

    Returns ``(world, package)``.
    """
    world = build_registered_world(api, **kwargs) if register else build_confirmed_world(api, **kwargs)
    package = draft_package(api, world.rating_id, world.builder_id, package_type)
    package = issue_package(api, package["id"])
    return world, package


@dataclass
class SampleWorld:
    """A sampling-enabled subdivision with a sample set and its member homes."""

    base: RatingWorld
    sample_set: Dict[str, Any]
    homes: List[Dict[str, Any]] = field(default_factory=list)
    ratings: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def sample_set_id(self) -> str:
        return self.sample_set["id"]

    @property
    def builder_id(self) -> str:
        return self.base.builder_id

    @property
    def subdivision_id(self) -> str:
        return self.base.subdivision_id

    @property
    def rater_id(self) -> str:
        return self.base.rater_id

    @property
    def inspector_id(self) -> str:
        return self.base.inspector_id


def build_sample_world(
    api: ApiClient,
    *,
    member_count: int = 3,
    lot_numbers: Optional[List[str]] = None,
    permit_dates: Optional[List[str]] = None,
    plan_overrides_per_home: Optional[List[Dict[str, Any]]] = None,
    window_start_date: str = "2026-08-01",
    window_end_date: str = "2026-08-31",
    add_members: bool = True,
    open_ratings: bool = True,
    **world_kwargs: Any,
) -> SampleWorld:
    """Tier 2/4 builder for the §3.5 sampling protocol.

    Creates the builder, a `sampling_enabled` subdivision, the certified people,
    one plan model (plus any extra plans named in ``plan_overrides_per_home``),
    ``member_count`` lots each with a PROJECTED rating, a FORMING sample set,
    and — unless ``add_members`` is false — every lot added to that set with the
    set's `version` re-read between additions as §2.9 requires.
    """
    world_kwargs.setdefault("sampling_enabled", True)
    world_kwargs.setdefault("subdivision_name", "Foxglove")
    world_kwargs.setdefault("builder_name", "Bristol Homes")
    base = build_rating_world(api, with_home=False, with_rating=False, **world_kwargs)

    lots = lot_numbers or [f"L-{4000 + index}" for index in range(member_count)]
    dates = permit_dates or ["2026-08-10"] * member_count

    homes: List[Dict[str, Any]] = []
    ratings: List[Dict[str, Any]] = []
    for index in range(member_count):
        overrides = (
            plan_overrides_per_home[index]
            if plan_overrides_per_home and plan_overrides_per_home[index]
            else None
        )
        plan_model_id = base.plan_model_id
        if overrides:
            plan_model_id = create_plan_model(
                api, base.subdivision_id, base.rater_id, **overrides
            )["id"]
        home = create_home(
            api,
            base.subdivision_id,
            plan_model_id,
            base.builder_id,
            lot_number=lots[index],
            permit_date=dates[index],
        )
        homes.append(home)
        if open_ratings:
            ratings.append(create_rating(api, home["id"], base.rater_id))

    sample_set = create_sample_set(
        api,
        base.subdivision_id,
        base.rater_id,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
    )
    if add_members:
        sample_set_id = sample_set["id"]
        for home in homes:
            add_sample_member(api, sample_set_id, home["id"], base.rater_id)
        # PRD never says which resource the membership endpoint returns, so the
        # set is re-read through its own GET route instead.
        sample_set = get_sample_set(api, sample_set_id)

    return SampleWorld(base=base, sample_set=sample_set, homes=homes, ratings=ratings)


def rating_of_home(api: ApiClient, home_id: str) -> Optional[Dict[str, Any]]:
    """The single live rating on a home, read through the §4 list endpoint."""
    data, _meta = validate_paginated(
        api.list_ratings(ADMIN_HEADERS, params={"home_id": home_id})
    )
    return data[0] if data else None


# ------------------------------------------------------------ layered fixtures
@pytest.fixture
def rating_world(api: ApiClient) -> RatingWorld:
    return build_rating_world(api)


@pytest.fixture
def confirmed_passing_world(api: ApiClient) -> RatingWorld:
    """Blower door 1080 CFM50 -> 3.00 ACH50 (PASS), duct 96 CFM25 -> 4.00 (PASS),
    confirmed index 46 against an `IECC_2021` / `CZ4` ERI target of 55."""
    return build_confirmed_world(api)


@pytest.fixture
def confirmed_failing_world(api: ApiClient) -> RatingWorld:
    """Blower door 1200 CFM50 -> 3.33 ACH50 (FAIL) leaves compliance FAILING."""
    return build_confirmed_world(api, blower_door=1200, duct_leakage=96)


@pytest.fixture
def registered_world(api: ApiClient) -> RatingWorld:
    return build_registered_world(api)


@pytest.fixture
def sample_world(api: ApiClient) -> SampleWorld:
    return build_sample_world(api)


@pytest.fixture
def selected_sample_world(api: ApiClient) -> SampleWorld:
    world = build_sample_world(api)
    world.sample_set = select_sample_set(api, world.sample_set_id)
    return world

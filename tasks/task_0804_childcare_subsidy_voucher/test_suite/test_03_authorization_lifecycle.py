"""Voucher creation, activation, and lifecycle (PRD §3.4, §3.5, §2.6, §2.7).

Depth coverage for cross-entity activation gating, referential/safety precedence,
the suspend/reinstate cycle, and the two temporal-overlap rules; breadth coverage
for rate selection, missing-ceiling rejection, terminal lockdown, clock expiry, and
optimistic concurrency.
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    publish_income_standard, publish_rate_ceiling, create_family_with_activity,
    create_approved_determination, register_provider, create_licensed_provider,
    create_pending_authorization, get_family_version, setup_active_authorization,
    create_authorization_payload, TEST_USERS,
)

CW = TEST_USERS["caseworker_headers"]
PA = TEST_USERS["program_admin_headers"]


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / activate_requires_provider_licensed
# ---------------------------------------------------------------------------
def test_activate_with_unlicensed_provider_rejected(api):
    """PRD §3.5: "the selected provider must be currently licensed — its
    `license_status` must be `LICENSED` — or the request is rejected with
    `ERR_PROVIDER_NOT_LICENSED`."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_provider_licensed
    """
    publish_income_standard()
    publish_rate_ceiling()
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = register_provider()  # left PENDING_VERIFICATION
    auth = create_pending_authorization(family["id"], provider["id"], det["id"])
    resp = api.activate_authorization(auth["id"], CW)
    validate_error(resp, ApiErrorId.ERR_PROVIDER_NOT_LICENSED)


def test_activate_succeeds_once_provider_licensed(api):
    """PRD §3.5: "When all three hold, the voucher moves from `PENDING` to `ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/activate_requires_provider_licensed
    """
    publish_income_standard()
    publish_rate_ceiling()
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = create_licensed_provider()
    auth = create_pending_authorization(family["id"], provider["id"], det["id"])
    data = validate_success(api.activate_authorization(auth["id"], CW), 200)
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / referential_beats_safety_on_authorization_activate
# ---------------------------------------------------------------------------
def _setup_family_mismatch_and_unlicensed():
    publish_income_standard()
    publish_rate_ceiling()
    fam_a = create_family_with_activity(applicant_name="Fam A")
    fam_b = create_family_with_activity(applicant_name="Fam B")
    det_b = create_approved_determination(fam_b["id"], "INITIAL")
    provider = register_provider(name="Unverified Center")  # PENDING_VERIFICATION
    fam_a_v = get_family_version(fam_a["id"])
    auth = validate_success(api_create_auth(fam_a["id"], provider["id"], det_b["id"],
                                            fam_a_v, child_name="Kid A"), 201)
    return auth


def api_create_auth(family_id, provider_id, determination_id, version, **overrides):
    from test_helpers import api_client
    return api_client.create_authorization(
        create_authorization_payload(family_id, provider_id, determination_id, version,
                                     **overrides), CW)


def test_family_mismatch_reported_before_provider_not_licensed(api):
    """PRD §3.5: "the determination's `family_id` must equal the voucher's `family_id`,
    or the request is rejected with `ERR_DETERMINATION_FAMILY_MISMATCH`. Second, the
    selected provider must be currently licensed"

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_authorization_activate
    """
    auth = _setup_family_mismatch_and_unlicensed()
    resp = api.activate_authorization(auth["id"], CW)
    validate_error(resp, ApiErrorId.ERR_DETERMINATION_FAMILY_MISMATCH)


def test_family_mismatch_precedence_returns_409(api):
    """PRD §2.9: "Only after these universal gates pass does the system evaluate the
    operation-specific business rules described in §3, in the relative order stated
    there."
    PRD §3.5: "the determination's `family_id` must equal the voucher's `family_id`,
    or the request is rejected with `ERR_DETERMINATION_FAMILY_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/referential_beats_safety_on_authorization_activate
    """
    auth = _setup_family_mismatch_and_unlicensed()
    resp = api.activate_authorization(auth["id"], CW)
    assert resp.status_code == 409
    body = resp.json()
    assert body["data"]["error_id"] == "ERR_DETERMINATION_FAMILY_MISMATCH"


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / authorization_suspend_reinstate_cycle
# ---------------------------------------------------------------------------
def test_suspend_moves_active_voucher_to_suspended(api):
    """PRD §3.5: "Suspension moves the voucher from `ACTIVE` to `SUSPENDED` and, as its
    own cascade hop, rejects every `SUBMITTED` attendance record for that voucher"

    Design: Difficulty/non_linear_state_machine/authorization_suspend_reinstate_cycle
    """
    ctx = setup_active_authorization()
    data = validate_success(api.suspend_authorization(ctx["authorization"]["id"], CW), 200)
    assert data["status"] == "SUSPENDED"


def test_reinstate_returns_suspended_voucher_to_active(api):
    """PRD §3.5: "A `SUSPENDED` voucher can be reinstated by a `CaseWorker`, moving it
    back from `SUSPENDED` to `ACTIVE`, but only if the provider's `license_status` is
    still `LICENSED`; otherwise reinstatement is rejected with `ERR_PROVIDER_NOT_LICENSED`."

    Design: Difficulty/non_linear_state_machine/authorization_suspend_reinstate_cycle
    """
    ctx = setup_active_authorization()
    auth_id = ctx["authorization"]["id"]
    api.suspend_authorization(auth_id, CW)
    data = validate_success(api.reinstate_authorization(auth_id, CW), 200)
    assert data["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / authorization_halfopen_interval_overlap
# ---------------------------------------------------------------------------
def _setup_first_authorization():
    publish_income_standard()
    publish_rate_ceiling()
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = create_licensed_provider()
    first = create_pending_authorization(
        family["id"], provider["id"], det["id"], child_name="Kid One",
        start_date="2026-03-01T00:00:00Z", end_date="2026-09-01T00:00:00Z")
    return family, provider, det, first


def test_overlapping_authorization_for_same_child_rejected(api):
    """PRD §3.4: "overlap is measured on the half-open interval from `start_date` up to
    but not including `end_date`, so two vouchers that merely abut — one ending exactly
    where the next begins — are allowed, while any true overlap is rejected with
    `ERR_AUTHORIZATION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/authorization_halfopen_interval_overlap
    """
    family, provider, det, first = _setup_first_authorization()
    version = get_family_version(family["id"])
    resp = api.create_authorization(create_authorization_payload(
        family["id"], provider["id"], det["id"], version, child_name="Kid One",
        start_date="2026-06-01T00:00:00Z", end_date="2026-12-01T00:00:00Z"), CW)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZATION_OVERLAP)


def test_abutting_authorization_for_same_child_allowed(api):
    """PRD §3.4: "two vouchers that merely abut — one ending exactly where the next
    begins — are allowed, while any true overlap is rejected with
    `ERR_AUTHORIZATION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/authorization_halfopen_interval_overlap
    """
    family, provider, det, first = _setup_first_authorization()
    version = get_family_version(family["id"])
    resp = api.create_authorization(create_authorization_payload(
        family["id"], provider["id"], det["id"], version, child_name="Kid One",
        start_date="2026-09-01T00:00:00Z", end_date="2027-03-01T00:00:00Z"), CW)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / rate_ceiling_closed_interval_overlap
# ---------------------------------------------------------------------------
def test_rate_ceiling_sharing_endpoint_is_overlap(api):
    """PRD §3.4: "No two ceilings for the same `provider_type`, `care_level`, and
    `state_code` may have overlapping windows; because the windows are closed, even a
    shared endpoint counts as an overlap, and a conflicting publication is rejected
    with `ERR_RATE_CEILING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_ceiling_closed_interval_overlap
    """
    publish_rate_ceiling(effective_start="2026-01-01T00:00:00Z",
                         effective_end="2026-06-30T00:00:00Z")
    resp = api.create_rate_ceiling({
        "provider_type": "CENTER", "care_level": "TODDLER", "max_daily_rate_cents": 5200,
        "effective_start": "2026-06-30T00:00:00Z", "effective_end": "2026-12-31T00:00:00Z",
        "state_code": "CA",
    }, PA)
    validate_error(resp, ApiErrorId.ERR_RATE_CEILING_OVERLAP)


def test_rate_ceiling_disjoint_window_allowed(api):
    """PRD §3.4: "No two ceilings for the same `provider_type`, `care_level`, and
    `state_code` may have overlapping windows; because the windows are closed, even a
    shared endpoint counts as an overlap, and a conflicting publication is rejected
    with `ERR_RATE_CEILING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/rate_ceiling_closed_interval_overlap
    """
    publish_rate_ceiling(effective_start="2026-01-01T00:00:00Z",
                         effective_end="2026-06-30T00:00:00Z")
    resp = api.create_rate_ceiling({
        "provider_type": "CENTER", "care_level": "TODDLER", "max_daily_rate_cents": 5200,
        "effective_start": "2026-07-01T00:00:00Z", "effective_end": "2026-12-31T00:00:00Z",
        "state_code": "CA",
    }, PA)
    validate_success(resp, expected_status=201)


# ---------------------------------------------------------------------------
# Corner: calculations / authorized_rate_takes_provider_rate_when_below_ceiling
# ---------------------------------------------------------------------------
def test_authorized_rate_is_provider_rate_when_below_ceiling(api):
    """PRD §3.4: "the voucher's `authorized_daily_rate_cents` is set to the smaller of
    the provider's `published_daily_rate_cents` and the selected ceiling's
    `max_daily_rate_cents` (a plain integer minimum, no rounding)."

    Design: Corner/calculations/authorized_rate_takes_provider_rate_when_below_ceiling
    """
    publish_income_standard()
    publish_rate_ceiling(max_daily_rate_cents=5_000)
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = create_licensed_provider(published=4_500)
    auth = create_pending_authorization(family["id"], provider["id"], det["id"])
    assert auth["authorized_daily_rate_cents"] == 4_500


# ---------------------------------------------------------------------------
# Corner: validations / no_rate_ceiling_on_authorization_create_returns_422
# ---------------------------------------------------------------------------
def test_authorization_create_without_matching_ceiling_returns_422(api):
    """PRD §3.4: "If no ceiling covers the `start_date`, creation is rejected with
    `ERR_NO_RATE_CEILING`."

    Design: Corner/validations/no_rate_ceiling_on_authorization_create_returns_422
    """
    publish_income_standard()
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = create_licensed_provider()
    version = get_family_version(family["id"])
    resp = api.create_authorization(create_authorization_payload(
        family["id"], provider["id"], det["id"], version, care_level="INFANT"), CW)
    validate_error(resp, ApiErrorId.ERR_NO_RATE_CEILING)


# ---------------------------------------------------------------------------
# Corner: state_machines / authorization_activate_from_terminated_returns_409
# ---------------------------------------------------------------------------
def test_activate_terminated_authorization_returns_409(api):
    """PRD §2.9: "For any transition endpoint, the target resource must be in a state
    from which the transition is defined; otherwise the request is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/authorization_activate_from_terminated_returns_409
    """
    ctx = setup_active_authorization()
    auth_id = ctx["authorization"]["id"]
    validate_success(api.terminate_authorization(auth_id, CW), 200)
    resp = api.activate_authorization(auth_id, CW)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# Corner: state_machines / authorization_expires_on_clock_advance
# ---------------------------------------------------------------------------
def test_active_authorization_expires_when_clock_passes_end_date(api):
    """PRD §2.7: "Any `Authorization` currently `ACTIVE` whose `end_date` is strictly
    earlier than the new clock time transitions to `EXPIRED`."

    Design: Corner/state_machines/authorization_expires_on_clock_advance
    """
    ctx = setup_active_authorization()
    auth_id = ctx["authorization"]["id"]
    api.set_clock({"to_iso8601": "2026-10-01T00:00:00Z"}, PA)
    data = validate_success(api.get_authorization(auth_id, CW), 200)
    assert data["status"] == "EXPIRED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / occ_stale_family_version_returns_412
# ---------------------------------------------------------------------------
def test_stale_family_version_on_second_create_returns_412(api):
    """PRD §2.6: "If `expected_family_version` does not equal the household's current
    `version` (because some other writer has already advanced it since the client last
    read the family), the creation is rejected with `ERR_STALE_FAMILY_VERSION` and HTTP
    status 412"

    Design: Corner/cross_cutting_complexity_layers/occ_stale_family_version_returns_412
    """
    publish_income_standard()
    publish_rate_ceiling()
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = create_licensed_provider()
    stale_version = get_family_version(family["id"])
    # First create advances Family.version.
    create_pending_authorization(family["id"], provider["id"], det["id"],
                                 child_name="Kid One", expected_family_version=stale_version)
    # Second create still carries the pre-advance version.
    resp = api.create_authorization(create_authorization_payload(
        family["id"], provider["id"], det["id"], stale_version, child_name="Kid Two"), CW)
    validate_error(resp, ApiErrorId.ERR_STALE_FAMILY_VERSION)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers / family_version_increments_on_authorization_create
# ---------------------------------------------------------------------------
def test_authorization_create_increments_family_version_and_sets_active(api):
    """PRD §3.4: "It sets the household's `active_authorization_id` to the new voucher"
    PRD §3.4: "Because this reshapes the household, voucher creation increments
    `Family.version` by one."

    Design: Corner/cross_cutting_complexity_layers/family_version_increments_on_authorization_create
    """
    publish_income_standard()
    publish_rate_ceiling()
    family = create_family_with_activity()
    det = create_approved_determination(family["id"], "INITIAL")
    provider = create_licensed_provider()
    version_before = get_family_version(family["id"])
    auth = create_pending_authorization(family["id"], provider["id"], det["id"],
                                        expected_family_version=version_before)
    after = validate_success(api.get_family(family["id"], CW), 200)
    assert after["version"] == version_before + 1
    assert after["active_authorization_id"] == auth["id"]

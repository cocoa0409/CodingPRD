"""State-machine precondition and transition claims across entities
(Corner queue: state_machines section)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_estate, create_petition,
    create_open_estate_with_nominated_pr, create_estate_with_appointed_pr,
    create_independent_estate_with_appointed_pr,
    file_bond, file_claim, list_asset, schedule_hearing, set_clock,
    ApiErrorId, TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
REP = TEST_USERS["representative_headers"]


def test_grant_testate_without_will_returns_will_not_lodged(api):
    """PRD §3.2: "when the estate's `estate_type` is `TESTATE`, the petition's
    `will_lodged` must be true, failing which the grant is rejected with
    `ERR_WILL_NOT_LODGED`."

    Design: Corner/state_machines/grant_petition_testate_without_will_returns_will_not_lodged
    """
    est = create_estate(gross_estate_value_cents=300_000, estate_type="TESTATE")
    pet = create_petition(est["id"], will_lodged=False)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.grant_petition(pet["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_WILL_NOT_LODGED)
    pet_after = get_success_data(api.get_petition(pet["id"], CLERK))
    assert pet_after["status"] == "PENDING"


def test_grant_already_granted_petition_returns_invalid_state(api):
    """PRD §3.2: "The grant is permitted only when the governing estate is still in
    `DRAFT` (otherwise `ERR_INVALID_STATE`)". PRD §3.2: "Both `GRANTED` and
    `DENIED` are terminal for the petition."

    A second grant (estate already OPEN, petition already GRANTED) is rejected.

    Design: Corner/state_machines/grant_already_granted_petition_returns_invalid_state
    """
    est = create_estate(gross_estate_value_cents=300_000)
    pet = create_petition(est["id"])
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.grant_petition(pet["id"], {"expected_estate_version": v}, JUDGE))
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.grant_petition(pet["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    pet_after = get_success_data(api.get_petition(pet["id"], CLERK))
    assert pet_after["status"] == "GRANTED"


def test_deny_petition_without_reason_returns_missing_field(api):
    """PRD §3.2: "Denial likewise requires the estate to be in `DRAFT`
    (`ERR_INVALID_STATE`) and requires a recorded `denial_reason`; if that reason is
    absent the request fails with `ERR_MISSING_FIELD`."

    Design: Corner/state_machines/deny_petition_without_reason_returns_missing_field
    """
    est = create_estate(gross_estate_value_cents=300_000)
    pet = create_petition(est["id"])
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.deny_petition(pet["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_MISSING_FIELD)


def test_appoint_full_estate_without_approved_bond_returns_bond_not_approved(api):
    """PRD §3.3: "When the representative's `bond_required` is true, a `Bond`
    backing this representative must already be `APPROVED`, failing which the
    request is rejected with `ERR_BOND_NOT_APPROVED`."

    A FULL estate with only a FILED (not APPROVED) bond cannot appoint.

    Design: Corner/state_machines/appoint_full_estate_without_approved_bond_returns_bond_not_approved
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    file_bond(est["id"], rep["id"], penal_amount_cents=3_250_000)   # FILED, not approved
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.appoint_representative(rep["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_BOND_NOT_APPROVED)
    rep_after = get_success_data(api.get_representative(rep["id"], CLERK))
    assert rep_after["status"] == "NOMINATED"


def test_approve_bond_below_required_returns_bond_insufficient(api):
    """PRD §3.3: "A judge approving a bond advances it `FILED → APPROVED`, permitted
    only when the bond's `penal_amount_cents` is greater than or equal to its
    `required_amount_cents`; a shortfall is rejected with `ERR_BOND_INSUFFICIENT`."

    Design: Corner/state_machines/approve_bond_below_required_returns_bond_insufficient
    """
    est, pet, rep = create_open_estate_with_nominated_pr(gross=6_000_000)
    bond = file_bond(est["id"], rep["id"], penal_amount_cents=3_249_999)
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.approve_bond(bond["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_BOND_INSUFFICIENT)
    bond_after = get_success_data(api.get_bond(bond["id"], CLERK))
    assert bond_after["status"] == "FILED"


def test_allow_claim_amount_exceeds_claimed_returns_allowed_amount_invalid(api):
    """PRD §3.5: "the amount the representative allows, `allowed_amount_cents`, must
    be greater than zero and no greater than the `claimed_amount_cents`, failing
    which the request is rejected with `ERR_ALLOWED_AMOUNT_INVALID`."

    Design: Corner/state_machines/allow_claim_amount_exceeds_claimed_returns_allowed_amount_invalid
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()
    claim = file_claim(est["id"], "GENERAL", 100_000, "C")
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.allow_claim(
        claim["id"], {"allowed_amount_cents": 200_000, "expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_ALLOWED_AMOUNT_INVALID)
    claim_after = get_success_data(api.get_claim(claim["id"], CLERK))
    assert claim_after["status"] == "FILED"


def test_marshal_from_listed_returns_invalid_state(api):
    """PRD §3.6: "Marshaling an appraised asset advances it `APPRAISED → MARSHALED`".
    PRD §3.6: "Appraising an asset advances it `LISTED → APPRAISED`".

    Marshaling a LISTED (never appraised) asset is not a valid from-state, so it is
    rejected with ERR_INVALID_STATE (PRD §2.11 names ERR_INVALID_STATE for a bad
    from-state).

    Design: Corner/state_machines/marshal_from_listed_returns_invalid_state
    """
    est, pet, rep = create_independent_estate_with_appointed_pr()
    asset = list_asset(est["id"], "CASH", 100_000, "X")
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.marshal_asset(asset["id"], {"expected_estate_version": v}, REP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    asset_after = get_success_data(api.get_asset(asset["id"], CLERK))
    assert asset_after["status"] == "LISTED"


def test_hold_hearing_before_start_returns_invalid_state(api):
    """PRD §3.11: "A judge conducts a scheduled hearing by holding it, advancing it
    `SCHEDULED → HELD`, permitted only when the current logical clock is at or after
    the hearing's `start_at` (`ERR_INVALID_STATE`)".

    Clock is at the default 2026-05-01; a hearing starting 2026-06-01 cannot be held.

    Design: Corner/state_machines/hold_hearing_before_start_returns_invalid_state
    """
    est = create_estate(gross_estate_value_cents=300_000)
    hearing = schedule_hearing(est["id"], "C1", "judge-1",
                               "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    resp = api.hold_hearing(hearing["id"], {"expected_estate_version": v}, JUDGE)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    hearing_after = get_success_data(api.get_hearing(hearing["id"], CLERK))
    assert hearing_after["status"] == "SCHEDULED"


def test_vacate_then_reschedule_frees_courtroom(api):
    """PRD §3.11: "A judge may instead vacate a scheduled hearing, advancing it
    `SCHEDULED → VACATED`, which carries `expected_estate_version`
    (`ERR_STALE_VERSION`), frees that courtroom and judge interval so it no longer
    collides with future scheduling". PRD §3.11: "A newly scheduled hearing enters
    `SCHEDULED` status, but only if it clears two independent conflict checks
    against other `SCHEDULED` hearings (`VACATED` and `HELD` hearings are excluded
    from both)."

    After vacating C1 10:00-11:00, an overlapping C1 10:30-11:30 (different judge)
    is accepted because the vacated hearing is excluded from the overlap set.

    Design: Corner/state_machines/vacate_then_reschedule_frees_courtroom
    """
    est = create_estate(gross_estate_value_cents=300_000)
    h1 = schedule_hearing(est["id"], "C1", "judge-1",
                          "2026-06-01T10:00:00Z", "2026-06-01T11:00:00Z")
    v = get_success_data(api.get_estate(est["id"], CLERK))["version"]
    validate_success(api.vacate_hearing(h1["id"], {"expected_estate_version": v}, JUDGE))

    resp = api.create_hearing({
        "estate_id": est["id"], "hearing_type": "ACCOUNTING",
        "courtroom_code": "C1", "judge_user_id": "judge-2",
        "start_at": "2026-06-01T10:30:00Z", "end_at": "2026-06-01T11:30:00Z",
    }, CLERK)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "SCHEDULED", (
        f"a vacated hearing should no longer conflict, got {data['status']}")

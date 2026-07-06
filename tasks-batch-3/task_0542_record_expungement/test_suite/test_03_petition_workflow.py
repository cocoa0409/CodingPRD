"""Petition lifecycle: DRAFT/SCREENED/FILED gates and validation precedence."""
from test_helpers import fixtures, validate_success, validate_error, ApiErrorId
from test_helpers.constants import CLOCK_START, STANDARD_MISDEMEANOR_FEE_CENTS

CLERK = fixtures.CLERK


# ---- file_state_beats_fee_unpaid (Difficulty) -----------------------------
def test_file_from_draft_unpaid_reports_invalid_state_not_fee_unpaid(api):
    """PRD §2.10: "6. **State** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."
    PRD §2.10: "A rule earlier in this list, when it fails, masks any later rule that
    would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/file_state_beats_fee_unpaid
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(api, p["id"])
    r = fixtures.screen_record(api, r["id"])  # ELIGIBLE
    petition = fixtures.create_petition(api, p["id"], [r["id"]])  # stays DRAFT
    # DRAFT->FILED is undefined (FILED only from SCREENED); fee also unpaid (fiscal, pri 11)
    resp = api.transition_petition(petition["id"], {"to_status": "FILED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_file_from_draft_with_unscreened_record_reports_invalid_state(api):
    """PRD §2.10: "6. **State** — the target resource is in a state from which the
    requested transition is defined, else `ERR_INVALID_STATE` (409)."
    PRD §2.10: "A rule earlier in this list, when it fails, masks any later rule that
    would also have failed."

    Design: Difficulty/priority_pair_validation_conflict/file_state_beats_fee_unpaid
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(api, p["id"])  # left UNSCREENED
    petition = fixtures.create_petition(api, p["id"], [r["id"]])  # DRAFT
    # Attempting FILED from DRAFT is a state violation; the state check (pri 6) masks
    # the unpaid-fee fiscal gate (pri 11).
    resp = api.transition_petition(petition["id"], {"to_status": "FILED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---- file_zero_eligible_records_empty_set (Difficulty) --------------------
def test_file_with_only_violent_felony_rejected_no_eligible_records(api):
    """PRD §3.5: "the petition must contain at least one item whose
    `eligibility_at_screening` is `ELIGIBLE`; a petition with no eligible records
    cannot be filed and is rejected with `ERR_NO_ELIGIBLE_RECORDS` (409)."

    Design: Difficulty/boundary_precision_check/file_zero_eligible_records_empty_set
    """
    specs = [{"offense_code": "PC-V", "offense_class": "VIOLENT_FELONY",
              "disposition": "CONVICTED", "disposition_date": "2018-01-01T00:00:00Z",
              "sentence_completion_date": "2019-01-01T00:00:00Z"}]
    ctx = fixtures.build_petition_with_records(api, specs, to_status="SCREENED")
    resp = api.transition_petition(ctx["petition"]["id"], {"to_status": "FILED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_RECORDS.value)


def test_file_with_only_waiting_period_record_rejected_no_eligible_records(api):
    """PRD §3.5: "the petition must contain at least one item whose
    `eligibility_at_screening` is `ELIGIBLE`; a petition with no eligible records
    cannot be filed and is rejected with `ERR_NO_ELIGIBLE_RECORDS` (409)."

    Design: Difficulty/boundary_precision_check/file_zero_eligible_records_empty_set
    """
    # MISDEMEANOR/CONVICTED sentence 2025-01-01 + 2y -> 2027-01-01 > clock -> WAITING_PERIOD
    specs = [{"offense_code": "PC-W", "offense_class": "MISDEMEANOR",
              "disposition": "CONVICTED", "disposition_date": "2024-01-01T00:00:00Z",
              "sentence_completion_date": "2025-01-01T00:00:00Z"}]
    ctx = fixtures.build_petition_with_records(api, specs, to_status="SCREENED")
    assert ctx["records"][0]["status"] == "INELIGIBLE"
    resp = api.transition_petition(ctx["petition"]["id"], {"to_status": "FILED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_RECORDS.value)


# ---- file_requires_eligible_record (Difficulty) ---------------------------
def test_file_succeeds_when_petition_has_an_eligible_record(api):
    """PRD §3.5: "the petition must contain at least one item whose
    `eligibility_at_screening` is `ELIGIBLE`; a petition with no eligible records
    cannot be filed and is rejected with `ERR_NO_ELIGIBLE_RECORDS` (409)."

    Design: Difficulty/cross_entity_state_dependency/file_requires_eligible_record
    """
    ctx = fixtures.setup_screened_petition(api)
    pet_id = ctx["petition"]["id"]
    fixtures.pay_fee(api, pet_id, STANDARD_MISDEMEANOR_FEE_CENTS)
    filed = validate_success(api.transition_petition(pet_id, {"to_status": "FILED"}, CLERK))
    assert filed["status"] == "FILED"


def test_file_final_fee_charges_the_eligible_record(api):
    """PRD §3.5: "the system computes `final_fee_cents` as the sum of the per-record
    fees — using the same per-record formula and round-then-sum order as in Section
    3.3 — but summed only over the items whose `eligibility_at_screening` is
    `ELIGIBLE`; because ineligible items drop out, the final fee is at most the
    provisional fee."

    Design: Difficulty/cross_entity_state_dependency/file_requires_eligible_record
    """
    ctx = fixtures.setup_screened_petition(api)
    pet_id = ctx["petition"]["id"]
    fixtures.pay_fee(api, pet_id, STANDARD_MISDEMEANOR_FEE_CENTS)
    filed = validate_success(api.transition_petition(pet_id, {"to_status": "FILED"}, CLERK))
    # single MISDEMEANOR/CONVICTED eligible record -> final fee 12900
    assert filed["final_fee_cents"] == STANDARD_MISDEMEANOR_FEE_CENTS


# ---- Corner: state_machines / validations / consistency -------------------
def test_new_petition_is_draft(api):
    """PRD §3.3: "Creating the petition places it in the `DRAFT` state and creates
    one `PetitionItem` junction row per entry in `record_ids`, each capturing a
    `petition_id` and a `record_id`."

    Design: Corner/state_machines/petition_initial_state_is_draft
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(api, p["id"])
    petition = validate_success(api.create_petition(
        {"petitioner_id": p["id"], "jurisdiction_code": "CA-01", "record_ids": [r["id"]]}, CLERK),
        expected_status=201)
    assert petition["status"] == "DRAFT"


def test_screen_transition_rejected_when_a_record_is_unscreened(api):
    """PRD §3.3: "Advancing a petition from `DRAFT` to `SCREENED` is a `Clerk` action
    and requires that the petition hold at least one `PetitionItem` and that every
    item's underlying record has already been screened — that is, each record's
    `status` is either `ELIGIBLE` or `INELIGIBLE`. If any included record is still
    `UNSCREENED`, the transition is rejected with `ERR_RECORDS_NOT_SCREENED` (409)."

    Design: Corner/state_machines/petition_screened_with_unscreened_record_rejected
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r1 = fixtures.create_record(api, p["id"], offense_code="PC-1")
    r2 = fixtures.create_record(api, p["id"], offense_code="PC-2",
                                offense_class="INFRACTION", disposition="ARREST_ONLY",
                                disposition_date="2020-01-01T00:00:00Z")
    fixtures.screen_record(api, r1["id"])  # only r1 screened; r2 still UNSCREENED
    petition = fixtures.create_petition(api, p["id"], [r1["id"], r2["id"]])
    resp = api.transition_petition(petition["id"], {"to_status": "SCREENED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_RECORDS_NOT_SCREENED.value)


def test_file_unpaid_no_waiver_rejected_filing_fee_unpaid(api):
    """PRD §3.5: "Filing is permitted only if the petition's fee is waived, or the
    `amount_paid_cents` already recorded is at least `final_fee_cents`; if neither
    holds, filing is rejected with `ERR_FILING_FEE_UNPAID` (402)."

    Design: Corner/validations/filing_fee_unpaid_isolated
    """
    ctx = fixtures.setup_screened_petition(api)
    resp = api.transition_petition(ctx["petition"]["id"], {"to_status": "FILED"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_FILING_FEE_UNPAID.value)


def test_petition_immediately_readable_after_create(api):
    """PRD §3.3: "It is assembled by the owning `Petitioner` or by a `Clerk`, naming
    the `petitioner_id`, the `jurisdiction_code` the petition is filed in, and a
    `record_ids` list identifying which of the petitioner's records to include.
    Creating the petition places it in the `DRAFT` state and creates one
    `PetitionItem` junction row per entry in `record_ids`, each capturing a
    `petition_id` and a `record_id`."

    Design: Corner/consistency_model/petition_immediately_readable_after_create
    """
    fixtures.set_clock(api, CLOCK_START)
    p = fixtures.create_petitioner(api)
    r = fixtures.create_record(api, p["id"])
    created = fixtures.create_petition(api, p["id"], [r["id"]], jurisdiction_code="CA-01")
    fetched = validate_success(api.get_petition(created["id"], CLERK))
    assert fetched["status"] == "DRAFT"
    assert fetched["jurisdiction_code"] == "CA-01"

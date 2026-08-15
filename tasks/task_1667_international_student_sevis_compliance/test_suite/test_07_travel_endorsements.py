"""Travel endorsement window overlap, state preconditions, and optimistic
concurrency claims (PRD §2.8, §3.6)."""
from test_helpers import (
    ApiErrorId,
    assert_travel_endorsement,
    get_i20_form,
    issue_endorsement,
    setup_active_student,
    setup_student_with_draft_i20,
    validate_error,
    validate_success,
)


class TestEndorsementWindowClosedTouchRejected:
    """Closed-interval travel windows: touching endpoints count as overlap."""

    def _setup(self, api):
        ctx = setup_active_student()
        i20_id = ctx["i20"]["id"]
        endorsement = issue_endorsement(i20_id, "2026-12-12", "2027-01-10")
        assert endorsement["status"] == "ACTIVE"
        form_version = get_i20_form(i20_id)["version"]
        return i20_id, form_version

    def test_touching_departure_rejected(self, api, dso_headers):
        """PRD §3.6: "Travel windows on one form follow closed-interval
        semantics: any intersection with the window of another `ACTIVE`
        endorsement counts as overlap, and touching endpoints — a new departure
        equal to an existing endorsement's return date — also count as overlap.
        A conflicting request is rejected with
        `ERR_ENDORSEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/endorsement_window_closed_touch_rejected
        """
        i20_id, version = self._setup(api)
        resp = api.create_travel_endorsement(
            i20_id,
            {"expected_i20_form_version": version,
             "travel_departure_date": "2027-01-10",  # == existing return date
             "travel_return_date": "2027-01-20"},
            dso_headers,
        )
        validate_error(resp, ApiErrorId.ERR_ENDORSEMENT_WINDOW_OVERLAP, 409)

    def test_next_day_departure_accepted_and_rejection_did_not_reprint(
        self, api, dso_headers,
    ):
        """PRD §3.6: "Travel windows on one form follow closed-interval
        semantics: any intersection with the window of another `ACTIVE`
        endorsement counts as overlap, and touching endpoints — a new departure
        equal to an existing endorsement's return date — also count as overlap.
        A conflicting request is rejected with
        `ERR_ENDORSEMENT_WINDOW_OVERLAP`."
        PRD §3.6: "Endorsement issuance is a reprint of the form: it increments
        the I20Form's `version` by one."

        Design: Difficulty/resource_temporal_overlap/endorsement_window_closed_touch_rejected
        """
        i20_id, version = self._setup(api)
        validate_error(
            api.create_travel_endorsement(
                i20_id,
                {"expected_i20_form_version": version,
                 "travel_departure_date": "2027-01-10",
                 "travel_return_date": "2027-01-20"},
                dso_headers,
            ),
            ApiErrorId.ERR_ENDORSEMENT_WINDOW_OVERLAP, 409,
        )
        # The rejected request must not have reprinted the form: the same
        # expected version still succeeds for a non-touching window.
        created = validate_success(
            api.create_travel_endorsement(
                i20_id,
                {"expected_i20_form_version": version,
                 "travel_departure_date": "2027-01-11",
                 "travel_return_date": "2027-01-20"},
                dso_headers,
            ),
            201,
        )
        assert_travel_endorsement(created)
        assert created["status"] == "ACTIVE"


def test_endorsement_on_draft_i20_returns_i20_not_issued(api, dso_headers):
    """PRD §3.6: "A travel endorsement is the re-entry signature placed on an
    issued I-20. A DSO issues one against an `ISSUED` form by supplying the
    intended `travel_departure_date` and `travel_return_date`".
    PRD §2.9: "6. **SEVIS structural preconditions.** Initialization requires
    an `ISSUED` I-20 (`ERR_NO_ISSUED_I20`); employment recommendation requires
    an `ISSUED` I-20 (`ERR_I20_NOT_ISSUED`) and an `ACTIVE` record;
    registration requires the record in `INITIAL` or `ACTIVE`; reinstatement
    recommendation requires the record `TERMINATED` (`ERR_RECORD_NOT_TERMINATED`)."

    Design: Corner/state_machines/endorsement_on_draft_i20_returns_i20_not_issued
    """
    ctx = setup_student_with_draft_i20()  # I-20 in DRAFT; OCC version current
    i20 = ctx["i20"]
    resp = api.create_travel_endorsement(
        i20["id"],
        {"expected_i20_form_version": i20["version"],
         "travel_departure_date": "2026-12-12",
         "travel_return_date": "2027-01-10"},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_I20_NOT_ISSUED, 409)


def test_endorsement_stale_i20_version_returns_412(api, dso_headers):
    """PRD §2.8: "Issuing a travel endorsement on an I-20 requires the request
    to carry `expected_i20_form_version` equal to that I20Form's current
    `version`. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)."
    PRD §3.6: "Endorsement issuance is a reprint of the form: it increments the
    I20Form's `version` by one."

    Design: Corner/cross_cutting_layers/endorsement_stale_i20_version_returns_412
    """
    ctx = setup_active_student()
    i20_id = ctx["i20"]["id"]
    version = get_i20_form(i20_id)["version"]

    first = validate_success(
        api.create_travel_endorsement(
            i20_id,
            {"expected_i20_form_version": version,
             "travel_departure_date": "2026-12-12",
             "travel_return_date": "2027-01-10"},
            dso_headers,
        ),
        201,
    )
    assert first["status"] == "ACTIVE"

    # The first issuance reprinted the form (version + 1), so the previously
    # observed version is now stale — even for a disjoint travel window.
    resp = api.create_travel_endorsement(
        i20_id,
        {"expected_i20_form_version": version,
         "travel_departure_date": "2027-02-01",
         "travel_return_date": "2027-02-20"},
        dso_headers,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
